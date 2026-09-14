(function () {
  "use strict";

  const DATA_URL =
    "https://cdn.jsdelivr.net/gh/llcbrein-pro/onco-portal@main/ordinatura/orp-data.json";

  const root = document.getElementById("oncoResidencyPortal");

  if (!root) {
    console.warn("Контейнер #oncoResidencyPortal не найден.");
    return;
  }

  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const normalizeModuleId = (value) =>
    String(value || "")
      .replace("М", "M")
      .replace("-", "")
      .trim();

  function showNotice(message, type = "info") {
    let node = root.querySelector("#orpSystemNotice");

    if (!node) {
      node = document.createElement("div");
      node.id = "orpSystemNotice";
      node.style.cssText =
        "margin:16px 0;padding:14px 16px;border-radius:12px;font:15px/1.45 Arial,sans-serif;";
      root.prepend(node);
    }

    const colors = {
      info: "background:#f2f5f7;color:#40515e;border:1px solid #dbe3e8;",
      error: "background:#fff2f2;color:#8a2d2d;border:1px solid #efcaca;",
      success: "background:#effaf4;color:#17653e;border:1px solid #bde5cf;"
    };

    node.style.cssText += colors[type] || colors.info;
    node.textContent = message;
  }

  function activatePanel(id) {
    root.querySelectorAll(".orp-navbtn").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.panel === id);
    });

    root.querySelectorAll(".orp-panel").forEach((panel) => {
      panel.classList.toggle("is-active", panel.dataset.panelId === id);
    });
  }

  function setupNavigation() {
    root.querySelectorAll(".orp-navbtn").forEach((button) => {
      button.addEventListener("click", () => {
        activatePanel(button.dataset.panel);
      });
    });
  }

  function renderModules(data) {
    const grid = root.querySelector("#orpModuleGrid");
    const search = root.querySelector("#orpModuleSearch");

    if (!grid || !search) return;

    let selectedYear = "all";

    function card(module) {
      const cases = Array.isArray(module.clinical_case_titles)
        ? module.clinical_case_titles.length
        : 0;

      const vp = Array.isArray(module.virtual_patients)
        ? module.virtual_patients.length
        : 0;

      return `
        <article class="orp-card">
          <div class="orp-cardtop">
            <span class="orp-tag">${escapeHtml(module.module_id)}</span>
            <span class="orp-tag">${escapeHtml(module.pedagogical_year)} год</span>
          </div>
          <h3 class="orp-h3">${escapeHtml(module.module_title)}</h3>
          <div class="orp-muted">
            ${escapeHtml(module.actual_lecture_date || "")}
          </div>
          <div class="orp-stats">
            <span class="orp-tag">задачи ${cases}</span>
            <span class="orp-tag">тесты ${escapeHtml(module.test_questions || 0)}</span>
            <span class="orp-tag">VP ${vp}</span>
          </div>
          <button class="orp-primary orp-module-open"
            data-id="${escapeHtml(module.module_id)}">
            Открыть модуль
          </button>
        </article>
      `;
    }

    function openModule(id) {
      const module = data.modules.find((item) => item.module_id === id);
      const runner = root.querySelector("#orpModuleRunner");

      if (!module || !runner) return;

      const clinicalCases = Array.isArray(module.clinical_case_titles)
        ? module.clinical_case_titles
            .map((item) => `<li>${escapeHtml(item)}</li>`)
            .join("")
        : "";

      const questions = Array.isArray(module.oral_discussion_questions)
        ? module.oral_discussion_questions
            .slice(0, 8)
            .map((item) => `<li>${escapeHtml(item)}</li>`)
            .join("")
        : "";

      runner.innerHTML = `
        <div class="orp-runner">
          <div class="orp-cardtop">
            <span class="orp-tag">${escapeHtml(module.module_id)}</span>
            <span class="orp-tag">${escapeHtml(module.pedagogical_year)} год</span>
            <span class="orp-tag">${escapeHtml(module.actual_lecture_date || "")}</span>
          </div>

          <h3 class="orp-h3">${escapeHtml(module.module_title)}</h3>

          <div class="orp-stage">
            <b>Лекция</b>
            <p>${escapeHtml(module.lecture || "Материал будет добавлен.")}</p>
          </div>

          <div class="orp-stage">
            <b>Семинар и клинические задачи</b>
            <ol class="orp-list">${clinicalCases || "<li>Материалы будут добавлены.</li>"}</ol>
          </div>

          <div class="orp-stage">
            <b>Вопросы для обсуждения</b>
            <ol class="orp-list">${questions || "<li>Вопросы будут добавлены.</li>"}</ol>
          </div>

          <div class="orp-stage">
            <b>Самоконтроль</b>
            <p>Тестовых заданий по модулю: ${escapeHtml(module.test_questions || 0)}.</p>
            <button class="orp-primary" id="orpModuleTest">
              Запустить тест по модулю
            </button>
          </div>
        </div>
      `;

      const testButton = runner.querySelector("#orpModuleTest");

      if (testButton) {
        testButton.addEventListener("click", () => {
          const select = root.querySelector("#orpTestModule");

          if (select) {
            select.value = module.module_id;
            activatePanel("tests");
            startTest(data, module.module_id, 10);
          }
        });
      }

      runner.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function render() {
      const query = search.value.trim().toLowerCase();

      const items = data.modules.filter((module) => {
        const yearMatches =
          selectedYear === "all" ||
          String(module.pedagogical_year) === String(selectedYear);

        const text =
          `${module.module_id || ""} ${module.module_title || ""}`.toLowerCase();

        return yearMatches && text.includes(query);
      });

      grid.innerHTML = items.map(card).join("");

      grid.querySelectorAll(".orp-module-open").forEach((button) => {
        button.addEventListener("click", () => {
          openModule(button.dataset.id);
        });
      });
    }

    root.querySelectorAll(".orp-pill[data-year]").forEach((button) => {
      button.addEventListener("click", () => {
        root.querySelectorAll(".orp-pill[data-year]").forEach((item) => {
          item.classList.remove("is-active");
        });

        button.classList.add("is-active");
        selectedYear = button.dataset.year;
        render();
      });
    });

    search.addEventListener("input", render);

    render();
  }

  function renderLibrary(data) {
    const type = root.querySelector("#orpLibType");
    const search = root.querySelector("#orpLibSearch");
    const grid = root.querySelector("#orpLibGrid");

    if (!type || !search || !grid) return;

    function render() {
      const query = search.value.trim().toLowerCase();
      const items = data.library?.[type.value] || [];

      grid.innerHTML = items
        .filter((item) => JSON.stringify(item).toLowerCase().includes(query))
        .map((item) => {
          const title = item.title || item.name || item.id || "Материал";
          const subtitle =
            item.year ||
            item.access_normalized ||
            item.access ||
            item.category ||
            "";

          return `
            <article class="orp-card">
              <span class="orp-tag">${escapeHtml(item.id || "")}</span>
              <h3 class="orp-h3">${escapeHtml(title)}</h3>
              <div class="orp-muted">${escapeHtml(subtitle)}</div>
              ${
                item.url
                  ? `<a class="orp-btn orp-link" href="${escapeHtml(item.url)}"
                     target="_blank" rel="noopener">Открыть источник</a>`
                  : ""
              }
            </article>
          `;
        })
        .join("");
    }

    type.addEventListener("change", render);
    search.addEventListener("input", render);

    render();
  }

  function startTest(data, moduleId = "", count = 10) {
    const box = root.querySelector("#orpTestBox");

    if (!box) return;

    let pool = data.questions.filter((question) => {
      return !moduleId || normalizeModuleId(question.module) === moduleId;
    });

    pool = [...pool]
      .sort(() => Math.random() - 0.5)
      .slice(0, Math.min(count, pool.length));

    if (!pool.length) {
      box.innerHTML = `
        <div class="orp-runner">
          <h3 class="orp-h3">Вопросы пока не найдены</h3>
          <p>Для выбранного модуля нет доступных тестовых заданий.</p>
        </div>
      `;
      return;
    }

    let index = 0;
    let score = 0;

    function renderQuestion() {
      if (index >= pool.length) {
        box.innerHTML = `
          <div class="orp-runner">
            <h3 class="orp-h3">Результат: ${score} / ${pool.length}</h3>
            <p>Тест завершён. Повторите попытку, чтобы закрепить материал.</p>
          </div>
        `;
        return;
      }

      const question = pool[index];

      const options = question.options
        .map((text, itemIndex) => ({
          text,
          key: "ABCD"[itemIndex]
        }))
        .sort(() => Math.random() - 0.5);

      box.innerHTML = `
        <div class="orp-runner">
          <div class="orp-muted">
            ${escapeHtml(question.id || "")} · ${index + 1}/${pool.length}
          </div>
          <div class="orp-question">${escapeHtml(question.stem)}</div>
          ${options
            .map(
              (option) => `
                <button class="orp-choice" data-key="${option.key}">
                  ${escapeHtml(option.text)}
                </button>
              `
            )
            .join("")}
          <div id="orpTestFeedback"></div>
        </div>
      `;

      box.querySelectorAll(".orp-choice").forEach((button) => {
        button.addEventListener("click", () => {
          box.querySelectorAll(".orp-choice").forEach((item) => {
            item.disabled = true;
          });

          const correct = button.dataset.key === question.correct;

          if (correct) score += 1;

          button.classList.add(correct ? "is-good" : "is-bad");

          box.querySelector("#orpTestFeedback").innerHTML = `
            <div class="orp-feedback">
              <b>${correct ? "Верно" : "Неверно"}</b><br>
              ${escapeHtml(question.explanation || "")}
            </div>
            <button class="orp-primary" id="orpNextTest">Далее</button>
          `;

          box.querySelector("#orpNextTest").addEventListener("click", () => {
            index += 1;
            renderQuestion();
          });
        });
      });
    }

    renderQuestion();
  }

  function setupTests(data) {
    const moduleSelect = root.querySelector("#orpTestModule");
    const countSelect = root.querySelector("#orpTestN");
    const button = root.querySelector("#orpStartTest");

    if (!moduleSelect || !countSelect || !button) return;

    data.modules.forEach((module) => {
      moduleSelect.insertAdjacentHTML(
        "beforeend",
        `<option value="${escapeHtml(module.module_id)}">
          ${escapeHtml(module.module_id)} — ${escapeHtml(module.module_title)}
        </option>`
      );
    });

    button.addEventListener("click", () => {
      startTest(
        data,
        moduleSelect.value,
        Number(countSelect.value || 10)
      );
    });
  }

  function renderSimpleCards(data, key, gridId, runnerId, buttonClass, title) {
    const grid = root.querySelector(gridId);
    const runner = root.querySelector(runnerId);

    if (!grid || !runner) return;

    const items =
      key === "virtual_patients"
        ? data.virtual_patients || []
        : key === "osce"
        ? data.osce?.stations || []
        : data.tumor_board?.cases || [];

    grid.innerHTML = items
      .map((item) => {
        const id = item.id || "";
        const itemTitle = item.title || "Учебный материал";

        return `
          <article class="orp-card">
            <span class="orp-tag">${escapeHtml(id)}</span>
            <h3 class="orp-h3">${escapeHtml(itemTitle)}</h3>
            <button class="orp-primary ${buttonClass}"
              data-id="${escapeHtml(id)}">
              Открыть
            </button>
          </article>
        `;
      })
      .join("");

    grid.querySelectorAll(`.${buttonClass}`).forEach((button) => {
      button.addEventListener("click", () => {
        const item = items.find((entry) => entry.id === button.dataset.id);

        if (!item) return;

        runner.innerHTML = `
          <div class="orp-runner">
            <span class="orp-tag">${escapeHtml(item.id || "")}</span>
            <h3 class="orp-h3">${escapeHtml(item.title || title)}</h3>
            <pre style="white-space:pre-wrap;font:14px/1.5 Arial,sans-serif;">
${escapeHtml(JSON.stringify(item, null, 2))}
            </pre>
          </div>
        `;

        runner.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  async function init() {
    try {
      showNotice("Загрузка учебных материалов…", "info");

      const response = await fetch(DATA_URL);

      if (!response.ok) {
        throw new Error(`Ошибка загрузки: ${response.status}`);
      }

      const data = await response.json();

      const notice = root.querySelector("#orpSystemNotice");

      if (notice) notice.remove();

      setupNavigation();
      renderModules(data);
      renderLibrary(data);
      setupTests(data);

      renderSimpleCards(
        data,
        "virtual_patients",
        "#orpVpGrid",
        "#orpVpRunner",
        "orp-vp-open",
        "Виртуальный пациент"
      );

      renderSimpleCards(
        data,
        "osce",
        "#orpOsceGrid",
        "#orpOsceRunner",
        "orp-osce-open",
        "OSCE"
      );

      renderSimpleCards(
        data,
        "tumor_board",
        "#orpTbGrid",
        "#orpTbRunner",
        "orp-tb-open",
        "Tumor Board"
      );

      const params = new URLSearchParams(window.location.search);
      const moduleId = params.get("module");

      if (moduleId) {
        activatePanel("modules");
      }
    } catch (error) {
      console.error(error);

      showNotice(
        "Не удалось загрузить учебные данные. Проверьте наличие файла orp-data.json в GitHub и обновите страницу.",
        "error"
      );
    }
  }

  init();
})();
