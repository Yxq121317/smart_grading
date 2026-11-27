const DEFAULT_EXAM_CODE = '2023-新高考Ⅰ卷';
let EXAM_CODE = DEFAULT_EXAM_CODE;
const API_BASE = '/api';

const ERROR_NAMES = {
  info_filter: '信息筛选错误',
  concept_misread: '概念理解偏差',
  incomplete_summary: '概括不全',
  argument_analysis: '论证分析错误',
  evidence_misuse: '论据使用不当',
  expression: '表达不规范',
  off_topic: '答非所问',
  blank: '未作答',
  mcq_wrong: '选择题误选',
};

const icons = {
  check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',
  alert: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.7 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z"/></svg>',
  sun: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z"/></svg>',
};

const state = {
  dashboard: null,
  selectedStudentId: null,
  selected: null,
  busy: false,
};

let examData = {
  exam: null,
  questions: [],
  students: [],
  selectedStudent: null,
  run: null,
  kpis: null,
  errorCategories: [],
  errorNames: ERROR_NAMES,
};

const $ = (selector) => document.querySelector(selector);

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[character]));
}

function formatScore(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number.isInteger(Number(value)) ? String(value) : Number(value).toFixed(1);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (error) {
      // Keep status text.
    }
    throw new Error(detail);
  }
  return response.json();
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 2400);
}

function setStatus(message, kind = 'info', actionLabel = null, action = null) {
  const status = $('#data-status');
  status.hidden = false;
  status.className = `data-status ${kind}`;
  status.innerHTML = `<span>${esc(message)}</span>`;
  if (actionLabel && action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn';
    button.style.marginLeft = '10px';
    button.textContent = actionLabel;
    button.addEventListener('click', action);
    status.appendChild(button);
  }
}

function hideStatus() {
  const status = $('#data-status');
  status.hidden = true;
  status.textContent = '';
}

function setRunNote(message, kind = 'info') {
  const note = $('#run-note');
  if (!note) return;
  if (!message) {
    note.hidden = true;
    note.textContent = '';
    return;
  }
  note.hidden = false;
  note.className = `run-note ${kind}`;
  note.textContent = message;
}

function markButtonBusy(button, label = '批改中…') {
  button.disabled = true;
  button.classList.add('is-busy');
  button.textContent = label;
}

function runStatusText(status) {
  return {
    pending: '未批改',
    running: '批改中',
    awaiting_review: '待复核',
    completed: '已批改',
    failed: '批改失败',
  }[status] || '未批改';
}

function statusOf(question) {
  if (question.resultId === null || question.resultId === undefined) {
    return { key: 'pending', label: '未批改' };
  }
  if (question.reviewed) return { key: 'reviewed', label: '已复核' };
  if (question.needsReview) return { key: 'warning', label: '待复核' };
  return { key: 'good', label: '已批改' };
}

function statusChip(question) {
  const status = statusOf(question);
  const icon = status.key === 'warning' ? icons.alert : status.key === 'pending' ? '' : icons.check;
  return `<span class="status ${status.key}">${icon}${status.label}</span>`;
}

function buildViewModel(data) {
  const exam = data.exam;
  const selectedStudent = data.selected_student;
  const run = selectedStudent?.run || null;
  const submission = selectedStudent?.submission || null;
  const results = new Map((run?.results || []).map((result) => [result.question_id, result]));
  const answers = new Map(
    (submission?.answers || []).map((answer) => [answer.question_id, answer]),
  );

  const questions = (exam?.questions || []).map((question) => {
    const result = results.get(question.id) || null;
    const answer = answers.get(question.id) || null;
    const selectedOptions = answer?.selected_options || [];
    const rubricPoints = question.active_rubric?.points || [];
    const pointMax = new Map(rubricPoints.map((point) => [point.id, point.score]));
    const pointResults = (result?.point_results || []).map((point) => ({
      status: point.hit ? 'hit' : point.score > 0 ? 'partial' : 'miss',
      text: point.comment || point.evidence || point.point_id,
      score: point.score,
      max: pointMax.get(point.point_id) ?? null,
    }));
    const aiScore = result ? Number(result.ai_score) : null;
    const finalScore = result ? Number(result.final_score) : null;
    const score = result ? (result.reviewed ? finalScore : aiScore) : null;
    const maxScore = result ? Number(result.max_score) : Number(question.max_score || 0);
    const needsReview = Boolean(result?.needs_review && !result?.reviewed);
    return {
      questionId: question.id,
      resultId: result?.id ?? null,
      number: question.question_number,
      type: question.question_type,
      stem: question.stem,
      options: question.options || [],
      correctAnswer: question.correct_answer,
      maxScore,
      aiScore,
      finalScore,
      score,
      confidence: result ? Number(result.confidence) : 0,
      needsReview,
      reviewed: Boolean(result?.reviewed),
      rationale: result?.rationale || '',
      errorType: result?.error_type || null,
      errorEvidence: result?.error_evidence || '',
      studentAnswer: answer?.answer_text || selectedOptions.join('、'),
      selectedOptions,
      points: pointResults,
      reviewReason: needsReview
        ? (result?.error_type
          ? ERROR_NAMES[result.error_type] || result.error_type
          : '置信度低于阈值')
        : '',
    };
  });

  const errorNames = data.error_type_names || ERROR_NAMES;
  const errorCategories = Object.entries(data.error_type_counts || {})
    .map(([code, count]) => ({
      code,
      name: errorNames[code] || ERROR_NAMES[code] || code,
      count: Number(count),
    }))
    .sort((a, b) => b.count - a.count);

  const selectedStillExists = questions.some(
    (question) => question.number === state.selected,
  );
  const firstReview = run?.review_items?.[0]?.question_number;
  if (!selectedStillExists) {
    state.selected = firstReview ?? questions[0]?.number ?? null;
  }

  examData = {
    exam,
    questions,
    students: data.students || [],
    selectedStudent,
    run,
    kpis: data.kpis,
    errorCategories,
    errorNames,
    configured: Boolean(data.configured),
    classInfo: data.class,
  };
  state.dashboard = data;
  state.selectedStudentId = selectedStudent?.id ?? null;
}

async function loadDashboard(studentId = null, { silent = false } = {}) {
  if (!silent) setStatus('正在加载后端数据...', 'info');
  const params = new URLSearchParams({ exam_code: EXAM_CODE });
  if (studentId) params.set('student_id', String(studentId));
  try {
    const data = await api(`${API_BASE}/demo/dashboard?${params.toString()}`);
    if (studentId && state.selectedStudentId !== studentId) {
      state.selected = null;
    }
    buildViewModel(data);
    hideStatus();
    renderAll();
    scheduleRunRefresh();
    if (!data.configured) {
      setStatus(
        '还没有班级和答卷数据。先生成 10 份模拟答卷，再选择学生开始批改。',
        'warning',
        '生成模拟班级和答卷',
        seedDemo,
      );
    }
  } catch (error) {
    setStatus(
      `接口连接失败：${error.message}。请通过 ${window.location.origin}/ 打开页面。`,
      'error',
    );
  }
}

let refreshTimer = null;

function scheduleRunRefresh() {
  clearTimeout(refreshTimer);
  const status = examData.run?.status;
  if (status !== 'pending' && status !== 'running') return;
  refreshTimer = setTimeout(() => {
    loadDashboard(state.selectedStudentId, { silent: true });
  }, 2500);
}

async function seedDemo() {
  setStatus('正在生成模拟班级和答卷（不调用模型）...', 'info');
  try {
    await api(`${API_BASE}/dev/seed-synthetic`, {
      method: 'POST',
      body: JSON.stringify({
        exam_code: EXAM_CODE,
        students: 10,
        class_name: '高二(1)班',
        seed: 42,
      }),
    });
    await loadDashboard();
    showToast('模拟班级和答卷已生成');
  } catch (error) {
    setStatus(`生成失败：${error.message}`, 'error');
  }
}

async function gradeCurrentSubmission() {
  const submission = examData.selectedStudent?.submission;
  if (!submission?.id) {
    showToast('没有可批改的答卷');
    renderDetail();
    return;
  }
  if (state.busy) {
    showToast('正在批改中，请稍候…');
    return;
  }
  state.busy = true;
  setStatus('正在启动批改，模型调用会产生少量 DeepSeek 费用...', 'info');
  setRunNote('正在提交批改任务…');
  try {
    const result = await api(`${API_BASE}/submissions/${submission.id}/grade`, {
      method: 'POST',
    });
    setStatus(`批改已启动（运行 ${result.grading_run_id}），等待模型返回...`, 'info');
    setRunNote(`第 ${result.grading_run_id} 次批改已启动，正在逐题评分…`);
    await pollRun(result.grading_run_id);
    await loadDashboard(state.selectedStudentId);
    showToast('批改完成');
  } catch (error) {
    setStatus(`批改失败：${error.message}`, 'error');
    renderDetail();
    setRunNote(`批改失败：${error.message}`, 'error');
  } finally {
    state.busy = false;
  }
}

async function pollRun(runId) {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    await sleep(1000);
    const run = await api(`${API_BASE}/grading-runs/${runId}`);
    if (run.status === 'pending' || run.status === 'running') {
      setRunNote(`模型正在逐题评分…已等待 ${attempt + 1} 秒`);
    }
    if (run.status === 'awaiting_review') {
      return run;
    }
    if (run.status === 'completed') {
      return run;
    }
    if (run.status === 'failed') {
      throw new Error(run.error || '批改运行失败');
    }
  }
  throw new Error('批改超时，请稍后刷新');
}

async function submitReview(question, score, instruction) {
  const run = examData.run;
  if (!run || !question.resultId) return;
  if (state.busy) return;
  state.busy = true;
  setStatus(`正在提交第 ${question.number} 题复核...`, 'info');
  try {
    await api(`${API_BASE}/grading-runs/${run.id}/review`, {
      method: 'POST',
      body: JSON.stringify({
        corrections: [
          {
            result_id: question.resultId,
            final_score: score,
            instruction,
          },
        ],
      }),
    });
    await pollRun(run.id);
    await loadDashboard(state.selectedStudentId);
    showToast(`第 ${question.number} 题已复核，最终 ${formatScore(score)} 分`);
  } catch (error) {
    setStatus(`复核失败：${error.message}`, 'error');
  } finally {
    state.busy = false;
  }
}

function renderHeader() {
  const exam = examData.exam;
  if (examData.configured && examData.classInfo) {
    $('#class-summary').textContent =
      `${examData.classInfo.name} · ${examData.classInfo.student_count} 人 · ${EXAM_CODE}`;
  } else {
    $('#class-summary').textContent = '还没有班级数据';
  }
  const student = examData.selectedStudent;
  $('#footer-summary').textContent = `${EXAM_CODE} · 数据来自 Mark 题库`;
  $('#footer-student').textContent = student
    ? `${student.name} · ${runStatusText(examData.run?.status)}`
    : '还没有学生数据';
  $('#data-mode').textContent = examData.configured ? '实时数据' : '等待数据';
  void exam;
}

async function loadExams() {
  const select = $('#exam-select');
  if (!select) return;
  try {
    const exams = await api(`${API_BASE}/exams`);
    if (!exams?.length) throw new Error('empty');
    select.innerHTML = exams
      .map((item) => `<option value="${esc(item.exam_code)}">${item.year} ${esc(item.paper_name)}</option>`)
      .join('');
    select.value = EXAM_CODE;
    if (!select.value) {
      EXAM_CODE = exams[0].exam_code;
      select.value = EXAM_CODE;
    }
  } catch (error) {
    select.innerHTML = `<option value="${esc(EXAM_CODE)}">${esc(EXAM_CODE)}</option>`;
    select.value = EXAM_CODE;
  }
}

function renderStudentSelect() {
  const select = $('#student-select');
  select.innerHTML = '';
  if (!examData.students.length) {
    const option = document.createElement('option');
    option.textContent = '暂无学生';
    select.appendChild(option);
    select.disabled = true;
    return;
  }
  select.disabled = false;
  for (const student of examData.students) {
    const option = document.createElement('option');
    option.value = String(student.id);
    option.textContent = `${student.name} · ${runStatusText(student.run_status)}`;
    select.appendChild(option);
  }
  if (examData.selectedStudent) {
    select.value = String(examData.selectedStudent.id);
  }
  select.onchange = () => loadDashboard(Number(select.value));
}

function renderPassage() {
  const passage = $('#passage');
  const paragraphs = examData.exam?.passage?.paragraphs || [];
  if (!paragraphs.length) {
    passage.innerHTML = '<p class="empty-state">还没有阅读材料。</p>';
    return;
  }
  passage.innerHTML = paragraphs
    .map((paragraph, index) => {
      const isSource = index === paragraphs.length - 1 && paragraph.trim().startsWith('（');
      return `<p${isSource ? ' class="source"' : ''}>${esc(paragraph)}</p>`;
    })
    .join('');
}

function renderKpis() {
  const kpis = examData.kpis;
  if (!kpis) {
    $('#kpi-average').innerHTML = '—<span>/ —</span>';
    $('#pending-count').innerHTML = '—<span>项</span>';
    $('#kpi-no-change').innerHTML = '—<span>%</span>';
    $('#kpi-completion').innerHTML = '—<span>/ —</span>';
    return;
  }
  const average = Number(kpis.average_score || 0);
  const maxScore = Number(kpis.max_score || 0);
  const pending = Number(kpis.pending_review || 0);
  const graded = Number(kpis.graded_count || 0);
  const students = Number(kpis.student_count || 0);
  const noChangeRate = Number(kpis.no_change_rate || 0);
  const completionRate = Number(kpis.completion_rate || 0);

  if (graded > 0) {
    $('#kpi-average').innerHTML = `${average.toFixed(1)}<span>/ ${maxScore.toFixed(1)}</span>`;
  } else {
    $('#kpi-average').innerHTML = '—<span>/ —</span>';
  }
  $('#kpi-average-note').textContent = `${students} 人 · ${graded} 份已批改`;
  $('#pending-count').innerHTML = `${pending}<span>项</span>`;
  $('#pending-note').textContent = pending ? `全班还有 ${pending} 项待复核` : '本卷复核完成';
  if (graded > 0) {
    $('#kpi-no-change').innerHTML = `${(noChangeRate * 100).toFixed(1)}<span>%</span>`;
    $('#kpi-no-change-note').textContent = '按已批改结果统计';
  } else {
    $('#kpi-no-change').innerHTML = '—<span>%</span>';
    $('#kpi-no-change-note').textContent = '还没有已完成批改';
  }
  $('#kpi-completion').innerHTML = `${graded}<span>/ ${students}</span>`;
  $('#kpi-completion-note').textContent = `完成 ${(completionRate * 100).toFixed(0)}%`;
  $('#kpi-completion-note').classList.add('good');
}

function renderQuestionList() {
  const list = $('#question-list');
  const questions = examData.questions;
  const choices = questions.filter((question) => question.type === 'single_choice').length;
  const subjective = questions.length - choices;
  $('#question-meta').textContent = questions.length
    ? `${questions.length} 题 · ${choices} 选择 / ${subjective} 主观`
    : '—';
  if (!questions.length) {
    list.innerHTML = '<p class="empty-state">还没有题目。</p>';
    return;
  }
  list.innerHTML = questions
    .map((question) => {
      const status = statusOf(question);
      const score = question.resultId === null
        ? '—'
        : `${formatScore(question.score)}/${question.maxScore}`;
      const type = question.type === 'single_choice' ? '选择' : '主观';
      return `
        <button class="q-item ${question.number === state.selected ? 'selected' : ''}" type="button" data-q="${question.number}" aria-pressed="${question.number === state.selected}">
          <span class="q-num">${question.number}</span>
          <span class="q-stem">${esc(question.stem)}</span>
          <span class="q-score"><span class="q-status ${status.key}">${status.label}</span> · ${score} · ${type}</span>
        </button>
      `;
    })
    .join('');
  list.querySelectorAll('.q-item').forEach((button) => {
    button.addEventListener('click', () => {
      state.selected = Number(button.dataset.q);
      renderQuestionList();
      renderDetail();
      if (window.matchMedia('(max-width: 960px)').matches) {
        $('#detail-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });
}

function renderOptions(question) {
  const selected = new Set(question.selectedOptions || []);
  const correct = question.correctAnswer
    || question.options.find((option) => option.is_correct)?.label;
  return `
    <div class="options">
      ${question.options.map((option) => {
        const isCorrect = option.label === correct;
        const isSelected = selected.has(option.label);
        const classes = ['option'];
        if (isCorrect) classes.push('correct');
        if (isSelected) classes.push('selected');
        if (isSelected && !isCorrect) classes.push('wrong');
        const tags = [
          isCorrect ? '<span class="option-tag good">正确答案</span>' : '',
          isSelected ? '<span class="option-tag selected">学生选择</span>' : '',
        ].join('');
        return `
          <div class="${classes.join(' ')}">
            <span class="option-label">${option.label}</span>
            <span class="option-text">${esc(option.content)}${tags ? `<span class="option-tags">${tags}</span>` : ''}</span>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderPoints(question) {
  if (!question.points.length) {
    return '<p class="empty-state">暂无采分点明细。</p>';
  }
  return `
    <ul class="points">
      ${question.points.map((point) => `
        <li class="${point.status}">
          <span class="point-icon ${point.status}" aria-hidden="true">${point.status === 'hit' ? '✓' : point.status === 'partial' ? '~' : '–'}</span>
          <span>${esc(point.text)}</span>
          <span class="point-score">${formatScore(point.score)}${point.max !== null ? `/${formatScore(point.max)}` : ''}</span>
        </li>
      `).join('')}
    </ul>
  `;
}

function renderReviewForm(question) {
  return `
    <form class="review-box" id="review-form">
      <p class="label">教师复核</p>
      <div class="review-grid">
        <div class="field">
          <label for="review-score">复核分数</label>
          <input id="review-score" name="score" type="number" min="0" max="${question.maxScore}" step="0.5" value="${formatScore(question.aiScore ?? 0)}" inputmode="decimal" />
        </div>
        <div class="field">
          <label for="review-instruction">修正说明</label>
          <textarea id="review-instruction" name="instruction" rows="2" placeholder="例如：第三点只要提到“倾向性标题”就给分"></textarea>
        </div>
      </div>
      <div class="actions">
        <button class="btn primary" type="submit">提交复核</button>
        <button class="btn" type="button" id="accept-ai">接受 AI 评分</button>
      </div>
      <p class="form-note">复核记录会保存，用于后续评分标准校准。</p>
    </form>
  `;
}

function renderRunState(question, run) {
  if (!run) {
    const hasSubmission = Boolean(examData.selectedStudent?.submission);
    const action = hasSubmission
      ? '<div class="action-row"><button class="btn primary" type="button" id="start-grade">开始批改</button></div>'
      : '<p class="empty-state">这份答卷还没有提交。先在页面上方生成模拟数据。</p>';
    return `
      <div class="run-state">
        <p><strong>还没有批改结果。</strong></p>
        ${action}
        <p class="run-note" id="run-note" hidden></p>
      </div>
    `;
  }
  if (run.status === 'pending' || run.status === 'running') {
    return `
      <div class="run-state">
        <p><strong>批改中。</strong>模型正在逐题评分，页面会自动刷新。</p>
        <p class="run-note" id="run-note">正在等待模型返回…</p>
        <p class="run-progress" aria-hidden="true"><span class="spinner"></span><span>逐题评分中，通常 10–30 秒</span></p>
      </div>
    `;
  }
  if (run.status === 'failed') {
    return `
      <div class="run-state">
        <p><strong>批改失败。</strong>${esc(run.error || '请重新启动批改。')}</p>
        <div class="action-row"><button class="btn primary" type="button" id="start-grade">重新批改</button></div>
        <p class="run-note" id="run-note" hidden></p>
      </div>
    `;
  }
  if (question.reviewed) {
    return `
      <div class="review-done">
        <span class="done-icon">${icons.check}</span>
        <div>
          <p class="done-title">已复核，最终得分 ${formatScore(question.finalScore)} 分</p>
          <p class="done-text">教师修正 ${formatScore(question.aiScore)} → ${formatScore(question.finalScore)} 分。${question.rationale ? ` 说明：${esc(question.rationale)}` : ''}</p>
        </div>
      </div>
    `;
  }
  if (run.status === 'awaiting_review' && question.needsReview) {
    return renderReviewForm(question);
  }
  if (run.status === 'awaiting_review') {
    return '<p class="form-note">本卷有复核项，但这道题不在复核队列里。</p>';
  }
  return '<p class="form-note">本卷批改已完成。</p>';
}

function renderDetail() {
  const panel = $('#detail-panel');
  const question = examData.questions.find(
    (item) => item.number === state.selected,
  );
  if (!question) {
    panel.innerHTML = '<div class="empty-state">还没有题目。</div>';
    return;
  }
  const isChoice = question.type === 'single_choice';
  const hasResult = question.resultId !== null;
  const confidence = Math.round(question.confidence * 100);
  const header = `
    <div class="detail-head">
      <div>
        <p class="eyebrow">第 ${question.number} 题 · ${isChoice ? '选择题' : '主观题'}</p>
        <h2>${esc(question.stem)}</h2>
      </div>
      ${statusChip(question)}
    </div>
  `;
  const answerBlock = isChoice
    ? renderOptions(question)
    : `
      <div class="answer-block">
        <p class="label">学生答案</p>
        <p class="student-answer">${question.studentAnswer ? esc(question.studentAnswer) : '未作答'}</p>
      </div>
    `;
  const scoreRow = hasResult
    ? `
      <div class="score-row">
        <div>
          <div class="score-big">${formatScore(question.score)}<span>/${formatScore(question.maxScore)}</span></div>
          ${question.reviewed ? `<p class="score-note">教师复核 · AI 原分 ${formatScore(question.aiScore)}</p>` : ''}
        </div>
        <div class="confidence">
          <p>${question.reviewed ? 'AI 置信度（复核前）' : 'AI 置信度'} ${confidence}%</p>
          <div class="meter" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${confidence}" aria-label="AI 置信度 ${confidence}%">
            <span style="width:${Math.max(0, Math.min(100, confidence))}%"></span>
          </div>
        </div>
      </div>
    `
    : '';
  const rubric = hasResult
    ? isChoice
      ? `
        <div class="rule-box">
          <p class="label">评分规则</p>
          <p>参考答案 <strong>${esc(question.correctAnswer || '—')}</strong>。选择题由规则精确比对。</p>
        </div>
      `
      : `
        <div class="rubric">
          <p class="label">AI 采分点</p>
          ${renderPoints(question)}
        </div>
      `
    : '';
  const rationale = hasResult
    ? `
      <div class="rationale">
        <p class="label">AI 评分理由</p>
        <p>${esc(question.rationale || '—')}</p>
      </div>
    `
    : '';
  panel.innerHTML = header + answerBlock + scoreRow + rubric + rationale + renderRunState(question, examData.run);
  bindDetail(question);
}

function bindDetail(question) {
  const startButton = $('#start-grade');
  if (startButton) {
    startButton.addEventListener('click', () => {
      if (state.busy) {
        showToast('正在批改中，请稍候…');
        return;
      }
      markButtonBusy(startButton);
      setRunNote('正在启动批改，模型调用会产生少量 DeepSeek 费用…');
      gradeCurrentSubmission();
    });
  }
  const form = $('#review-form');
  if (!form) return;
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const score = Number($('#review-score').value);
    if (!Number.isFinite(score) || score < 0 || score > question.maxScore) {
      showToast(`分数需要在 0–${question.maxScore} 之间`);
      return;
    }
    submitReview(question, score, $('#review-instruction').value.trim());
  });
  $('#accept-ai').addEventListener('click', () => {
    submitReview(question, question.aiScore, '教师接受 AI 评分');
  });
}

function renderReviewQueue() {
  const list = $('#review-list');
  const run = examData.run;
  const items = run?.review_items || [];
  $('#review-meta').textContent = `${items.length} 项`;
  if (!run) {
    list.innerHTML = `<li class="review-empty"><span class="empty-check">${icons.check}</span><span>本卷还没有批改结果。</span></li>`;
    return;
  }
  if (!items.length) {
    list.innerHTML = `<li class="review-empty"><span class="empty-check">${icons.check}</span><span>本卷没有待复核项。</span></li>`;
    return;
  }
  list.innerHTML = items.map((item) => `
    <li>
      <button class="review-item" type="button" data-q="${item.question_number}">
        <span>
          <span class="review-title">第 ${item.question_number} 题 · ${item.question_type === 'single_choice' ? '选择题' : '主观题'}</span>
          <span class="review-meta">${esc(examData.selectedStudent?.name || '')} · 置信度 ${Math.round(Number(item.confidence) * 100)}% · ${esc(ERROR_NAMES[item.error_type] || '低置信度')}</span>
        </span>
        <span class="review-score">AI ${formatScore(item.ai_score)}/${formatScore(item.max_score)}</span>
      </button>
    </li>
  `).join('');
  list.querySelectorAll('.review-item').forEach((button) => {
    button.addEventListener('click', () => {
      state.selected = Number(button.dataset.q);
      renderQuestionList();
      renderDetail();
      $('#detail-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

function renderErrorBars() {
  const bars = $('#error-bars');
  const categories = examData.errorCategories;
  const graded = Number(examData.kpis?.graded_count || 0);
  const total = categories.reduce((sum, item) => sum + item.count, 0);
  $('#error-meta').textContent = `${graded} 份已批改 · ${total} 条错因`;
  if (!categories.length) {
    bars.innerHTML = '<p class="empty-state">还没有已批改的错因数据。</p>';
    $('#error-table-body').innerHTML = '';
    return;
  }
  const max = Math.max(...categories.map((item) => item.count));
  bars.innerHTML = categories.map((item) => `
    <div class="bar-row" data-tip="${esc(item.name)} · ${item.count} 次" tabindex="0">
      <span class="bar-label">${esc(item.name)}</span>
      <span class="bar-track" aria-hidden="true"><span class="bar-fill" style="width:${(item.count / max) * 100}%"></span></span>
      <span class="bar-count">${item.count}</span>
    </div>
  `).join('');
  $('#error-table-body').innerHTML = categories.map((item) => `
    <tr><td>${esc(item.name)}</td><td>${item.count}</td></tr>
  `).join('');
  const tooltip = $('#tooltip');
  bars.querySelectorAll('.bar-row').forEach((row) => {
    row.addEventListener('pointerenter', (event) => {
      tooltip.textContent = row.dataset.tip;
      tooltip.classList.add('show');
      tooltip.style.left = `${event.clientX + 14}px`;
      tooltip.style.top = `${event.clientY - 30}px`;
    });
    row.addEventListener('pointermove', (event) => {
      tooltip.style.left = `${event.clientX + 14}px`;
      tooltip.style.top = `${event.clientY - 30}px`;
    });
    row.addEventListener('pointerleave', () => tooltip.classList.remove('show'));
  });
}

function renderAll() {
  renderHeader();
  renderStudentSelect();
  renderPassage();
  renderKpis();
  renderQuestionList();
  renderDetail();
  renderReviewQueue();
  renderErrorBars();
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const dark = theme === 'dark';
  const button = $('#theme-toggle');
  button.innerHTML = dark ? icons.sun : icons.moon;
  button.setAttribute('aria-label', dark ? '切换到浅色主题' : '切换到深色主题');
  try {
    localStorage.setItem('sg-theme', theme);
  } catch (error) {
    // Storage may be unavailable.
  }
}

function initTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem('sg-theme');
  } catch (error) {
    saved = null;
  }
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  setTheme(saved === 'light' || saved === 'dark' ? saved : (prefersDark ? 'dark' : 'light'));
}

$('#theme-toggle').addEventListener('click', () => {
  const current = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  setTheme(current === 'dark' ? 'light' : 'dark');
});

const examSelect = $('#exam-select');
if (examSelect) {
  examSelect.addEventListener('change', () => {
    EXAM_CODE = examSelect.value;
    state.selected = null;
    state.selectedStudentId = null;
    loadDashboard(null);
  });
}

$('#data-mode').addEventListener('click', () => {
  showToast(`数据来自 ${API_BASE}/demo/dashboard · 试卷 ${EXAM_CODE}`);
});

const importButton = $('#import-sheet');
const templateButton = $('#download-template');
const sheetFile = $('#sheet-file');

if (importButton && sheetFile) {
  importButton.addEventListener('click', () => sheetFile.click());
  sheetFile.addEventListener('change', uploadAnswerSheet);
}

if (templateButton) {
  templateButton.addEventListener('click', downloadTemplate);
}

async function uploadAnswerSheet() {
  const file = sheetFile?.files?.[0];
  if (!file) return;
  const examId = examData.exam?.id;
  if (!examId) {
    showToast('还没有加载到试卷，稍后再试');
    return;
  }
  const body = new FormData();
  body.append('file', file);
  body.append('class_name', examData.classInfo?.name || '导入班级');
  setStatus(`正在解析并导入 ${file.name} …`, 'info');
  try {
    const response = await fetch(`${API_BASE}/exams/${examId}/submissions/import`, {
      method: 'POST',
      body,
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        detail = (await response.json()).detail || detail;
      } catch (error) {
        // 保留状态文本。
      }
      throw new Error(detail);
    }
    const result = await response.json();
    await loadDashboard(state.selectedStudentId);
    const summary = `导入 ${result.created} 份答卷${result.skipped ? `，跳过 ${result.skipped} 份` : ''}`;
    if (result.errors?.length) {
      setStatus(`${summary}。${result.errors.slice(0, 3).join('；')}`, 'warning');
    } else {
      showToast(summary);
      hideStatus();
    }
  } catch (error) {
    setStatus(`导入失败：${error.message}`, 'error');
  } finally {
    if (sheetFile) sheetFile.value = '';
  }
}

function downloadTemplate() {
  const questions = examData.questions || [];
  if (!questions.length) {
    showToast('还没有题目，无法生成模板');
    return;
  }
  const headers = ['student_no', 'student_name', ...questions.map((question) => `Q${question.number}`)];
  const sample = ['2023999', '示例学生', ...questions.map((question) => (
    question.type === 'single_choice' ? 'A' : '主观题答案写在这里'
  ))];
  const csv = `\ufeff${headers.join(',')}\n${sample.join(',')}\n`;
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `答题卡模板-${EXAM_CODE}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

const passageWrap = $('#passage-wrap');
const passageButton = $('#toggle-passage');
passageButton.addEventListener('click', () => {
  const expanded = passageWrap.classList.toggle('expanded');
  passageButton.setAttribute('aria-expanded', String(expanded));
  passageButton.querySelector('span').textContent = expanded ? '收起' : '展开全文';
});

initTheme();
const urlStudentId = Number(new URLSearchParams(window.location.search).get('student_id'));
if (window.location.protocol === 'file:') {
  setStatus(
    '请通过后端地址打开页面（例如 http://127.0.0.1:8000/），file:// 无法访问接口。',
    'error',
  );
} else {
  loadExams().finally(() => {
    loadDashboard(
      Number.isFinite(urlStudentId) && urlStudentId > 0 ? urlStudentId : null,
    );
  });
}
